"""workers/canvas_page.py

中栏画布页（canvas）渲染 —— 把工作室产出的 markdown 渲染成一份自包含 HTML。

硬约束（三条都是刻意的，别随手破坏）：
  · 零 CDN / 零 JS / 单文件自包含 —— 一份产物三处可用：
      1) 中栏舞台 iframe 渲染（能圈字批注）
      2) 存成文件双击直接打开
      3) 托管到静态站原样渲染
  · 不引外部字体、不引图标库 —— 离线可用，网络风险为零
  · 不做滚动/加载动效 —— 画布页是「拿来反复读、反复批」的，动效是干扰

视觉意图（按 playbook「打造独特有意图的前端视觉设计方案」）：
  这个页面的核心动作是「批注」，所以取 宣纸 / 墨 / 朱砂 的批注母题——
  朱砂不是拿来当主色调的，是「批注笔」的颜色。
  刻意避开 AI 三种默认风格：朱砂只做点不做面（不是奶油底+陶土色块）·
  正文走无衬线（不是高对比衬线）· 疏排留白（不是报纸密排）。
  签名元素：贯穿的装订脊线 + 章节序号的朱砂小印（纯 CSS counter，零 JS）。

公共 API：
  render_canvas_html(title, body_md, ...) -> str     渲染（不落盘）
  write_canvas_for(md_rel_path, html) -> str         按 md 路径落同名 .html，返回相对路径
"""
from __future__ import annotations

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ──────────────────────────────────────────────────────────
# 设计令牌 · 就这几支笔，别再加
# ──────────────────────────────────────────────────────────
_CSS = """
:root{
  --paper:#fbf9f5;      /* 宣纸白 · 比纯白暖一点，比奶油冷一点 */
  --card:#ffffff;
  --ink:#1b1a18;        /* 墨 */
  --ink-2:#56514a;      /* 次级墨 · 正文 */
  --ink-3:#8d867c;      /* 淡墨 · 标签 */
  --rule:#e6e1d8;       /* 竹纸线 */
  --rule-soft:#f1ede5;
  --seal:#b8442e;       /* 朱砂 · 唯一强调色，只做点不做面 */
  --seal-wash:#f9efec;
  --jade:#3f6f5e;       /* 少量 · 只用于「已完成/通过」语义 */
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--paper); color:var(--ink-2);
  font-family:var(--sans); font-size:15.5px; line-height:1.78;
  -webkit-font-smoothing:antialiased;
}
/* 签名元素① · 装订脊线 */
.spine{
  position:fixed; left:0; top:0; bottom:0; width:3px;
  background:linear-gradient(180deg,var(--seal) 0%,var(--seal) 12%,var(--rule) 12%,var(--rule) 100%);
  opacity:.9;
}
.paper{
  max-width:820px; margin:0 auto; padding:56px 60px 72px;
  background:var(--card); min-height:100vh;
  border-left:1px solid var(--rule); border-right:1px solid var(--rule);
}
/* ── 页头 ── */
.hd{padding-bottom:22px; border-bottom:2px solid var(--ink)}
.hd-eyebrow{
  font-family:var(--mono); font-size:10.5px; letter-spacing:.16em;
  text-transform:uppercase; color:var(--ink-3); margin-bottom:12px;
}
.hd-title{margin:0; font-size:29px; line-height:1.28; letter-spacing:-.022em; color:var(--ink); font-weight:680}
.hd-meta{margin-top:12px; font-family:var(--mono); font-size:11.5px; color:var(--ink-3); display:flex; flex-wrap:wrap; gap:6px 14px}
.hd-meta b{color:var(--seal); font-weight:600}
/* ── 正文 ── */
.doc{counter-reset:sec; margin-top:8px}
.doc>*:first-child{margin-top:0}
.doc h2{
  counter-increment:sec; position:relative;
  margin:46px 0 14px; padding-left:44px;
  font-size:19.5px; line-height:1.45; letter-spacing:-.012em; color:var(--ink); font-weight:660;
}
/* 签名元素② · 章节序号的朱砂小印 */
.doc h2::before{
  content:counter(sec,decimal-leading-zero);
  position:absolute; left:0; top:.15em;
  font-family:var(--mono); font-size:10.5px; letter-spacing:.04em; line-height:1;
  color:#fff; background:var(--seal); border-radius:4px; padding:4px 6px;
}
.doc h3{margin:30px 0 10px; font-size:16.5px; letter-spacing:-.008em; color:var(--ink); font-weight:640}
.doc h4{margin:22px 0 8px; font-size:14.5px; color:var(--ink); font-weight:640}
.doc p{margin:12px 0}
.doc strong{color:var(--ink); font-weight:650}
.doc em{font-style:normal; color:var(--seal)}
.doc a{color:var(--seal); text-decoration:none; border-bottom:1px solid rgba(184,68,46,.34)}
.doc ul,.doc ol{margin:12px 0; padding-left:24px}
.doc li{margin:6px 0}
.doc ul>li::marker{color:var(--seal)}
.doc ol>li::marker{color:var(--ink-3); font-family:var(--mono); font-size:.9em}
.doc hr{border:0; height:1px; background:var(--rule); margin:36px 0}
/* 引用块 = 批注口吻 */
.doc blockquote{
  margin:18px 0; padding:12px 18px; border-left:3px solid var(--seal);
  background:var(--seal-wash); border-radius:0 10px 10px 0; color:var(--ink-2);
}
.doc blockquote p{margin:6px 0}
/* 表格 */
.doc table{
  width:100%; border-collapse:collapse; margin:18px 0;
  font-size:14px; border:1px solid var(--rule); border-radius:10px; overflow:hidden;
}
.doc th{
  background:#faf7f1; text-align:left; padding:10px 13px;
  font-family:var(--mono); font-size:10.5px; letter-spacing:.09em; text-transform:uppercase;
  color:var(--ink-3); font-weight:600; border-bottom:1px solid var(--rule);
}
.doc td{padding:10px 13px; border-bottom:1px solid var(--rule-soft); vertical-align:top}
.doc tr:last-child td{border-bottom:0}
/* 代码 */
.doc code{
  font-family:var(--mono); font-size:.88em; background:#f5f2eb;
  padding:1.5px 5px; border-radius:4px; color:var(--ink);
}
.doc pre{
  margin:16px 0; padding:14px 16px; background:#faf7f1;
  border:1px solid var(--rule); border-radius:10px; overflow:auto; line-height:1.6;
}
.doc pre code{background:none; padding:0; font-size:12.5px; color:var(--ink-2)}
/* ── 页脚 ── */
.ft{
  margin-top:56px; padding-top:16px; border-top:1px solid var(--rule);
  font-family:var(--mono); font-size:11px; color:var(--ink-3);
  display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap;
}
@media (max-width:720px){
  .paper{padding:32px 20px 48px; border:0}
  .hd-title{font-size:23px}
  .doc h2{padding-left:38px; font-size:18px}
  body{font-size:15px}
  .doc table{font-size:13px}
}
@media print{
  .spine{display:none}
  .paper{border:0; max-width:none; padding:0}
}
"""

_TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="spine"></div>
<main class="paper">
  <header class="hd">
    <div class="hd-eyebrow">{eyebrow}</div>
    <h1 class="hd-title">{title}</h1>
    <div class="hd-meta">{meta}</div>
  </header>
  <article class="doc">
{body}
  </article>
  <footer class="ft"><span>{footer_left}</span><span>{footer_right}</span></footer>
</main>
</body>
</html>
"""


def _md_renderer():
    """markdown-it · commonmark + 表格 + 删除线；关掉裸 HTML（保自包含 + 防模板被破）"""
    from markdown_it import MarkdownIt

    return (
        MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
        .enable("table")
        .enable("strikethrough")
    )


def _esc(s: str) -> str:
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_canvas_html(
    title: str,
    body_md: str,
    *,
    kind: str = "",
    domain: str = "",
    icon: str = "",
    label: str = "",
) -> str:
    """把 markdown 正文渲染成一份完整的自包含 HTML（不落盘）"""
    html_body = _md_renderer().render(body_md or "")

    eyebrow_bits = []
    if icon or label:
        eyebrow_bits.append((icon + " " + label).strip())
    if domain:
        eyebrow_bits.append(domain)
    if kind:
        eyebrow_bits.append(kind)
    eyebrow = " · ".join([b for b in eyebrow_bits if b]) or "Daemonkey 工作室"

    ts = time.strftime("%Y-%m-%d %H:%M")
    meta = f"<span>出品 <b>Daemonkey</b></span><span>{_esc(ts)}</span><span>画布页 · 可直接圈字批注</span>"

    return _TPL.format(
        title=_esc(title),
        css=_CSS,
        eyebrow=_esc(eyebrow),
        meta=meta,
        body=html_body,
        footer_left="Daemonkey 工作室 · 画布页",
        footer_right=_esc(title),
    )


def canvas_path_for(md_rel_path: str) -> Path:
    """`data/design/x.md` → `<ROOT>/data/design/x.html`（绝对路径）"""
    p = Path(str(md_rel_path))
    if not p.is_absolute():
        p = ROOT / p
    return p.with_suffix(".html")


def write_canvas_for(md_rel_path: str, html: str) -> str:
    """按 md 路径落同名 .html，返回相对 ROOT 的路径（正斜杠）"""
    target = canvas_path_for(md_rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return str(target.relative_to(ROOT)).replace("\\", "/")
