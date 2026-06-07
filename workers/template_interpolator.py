"""workers/template_interpolator.py
====================================

卷四十六续 13 · wish-165ea1f6 phase C · exec_template 用的最小模板插值器

支持的语法 (故意做窄·不允许任意表达式·避免变成 mini Jinja):

    ${ui:<field_name>}                  · 取 ui_form 字段值
    ${ui:<field_name>:<default>}        · 字段缺失/空时用默认值 (default 是字面量 · 不递归)

类型保留规则 (interpolate_deep 走的):
    - 字符串 "${ui:n}" 整体是单一 placeholder · ui.n=1 (int) → 返 1 (int · 类型保留)
    - 字符串 "size=${ui:size}" 字符串拼接 → 返 str (因为有非 placeholder 字符)
    - 跟 Terraform / jq / GoTemplate 一致 · 解决 API 期望 uint 我们却传 "1" str 的问题
    ${secret:<app_id>:<secret_name>}    · 铁律 7 标准 · workers.app_secrets.get_secret(app_id, name)
    ${secret:<secret_name>}             · 单段兜底 · 用 context.app_id (只能拿自己 app 的 secret)
    ${upstream:<node_id>:<port>}        · 工作流上游节点 output (workflow_engine 注入)
    ${app_id}                           · 当前 app id (后端注入)
    ${ts}                               · 时间戳 (yyyymmdd_HHMMSS · 后端注入)
    ${ts_ms}                            · 毫秒时间戳

secret 走 workers.app_secrets · 跟『卷四十四 K stage 2c++ · 铁律 7』对齐:
    - app KEY 存 data/workshop/secrets/<app_id>.json · 结构 {"app_id":"...","secrets":{"name":"value"}}
    - daemon OPUS 通过 app_set_secret 工具落盘 · 不会直接拿 value (LLM 只看 placeholder)
    - exec_template / system_prompt / shell_exec 里都用 placeholder · daemon 在内部 resolve

不支持:
    - 任意 Python 表达式
    - 条件 / 三元
    - 嵌套 (${ui:${ui:field}} 这种)
    - 算术 ($\{ui:a\} + $\{ui:b\})
    - 循环

如果需要这些·应该走 agentic + LLM·不要试图把 exec_template 写成图灵完备的 DSL。

使用:
    text = interpolate("https://x.com/${ui:endpoint}", context)
    obj  = interpolate_deep({"url": "...", "body": {"a": "${ui:x}"}}, context)
"""

from __future__ import annotations

import re
import time
from typing import Any


_PATTERN = re.compile(
    r"\$\{(?P<kind>ui|secret|upstream|app_id|ts|ts_ms)(?::(?P<rest>[^}]*))?\}"
)
# 整个字符串就是一个 ${...} placeholder (没有任何前后字符) · 类型保留路径用
_SINGLE_PATTERN = re.compile(
    r"^\$\{(?P<kind>ui|secret|upstream|app_id|ts|ts_ms)(?::(?P<rest>[^}]*))?\}$"
)


def _try_parse_default(s):
    """default 字符串 → 原生类型 (类型保留路径用) · 失败保留字符串
    
    '1' → 1 (int)  ·  '1.5' → 1.5 (float)  ·  '1024x1024' → '1024x1024' (str · 不识别)
    'true' / 'false' → bool
    """
    if s is None or s == "":
        return s
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if "." not in s and "e" not in low:
            return int(s)
        return float(s)
    except (TypeError, ValueError):
        return s


class TemplateError(Exception):
    """模板插值失败 · 字段缺失 / secret 没找到 / 语法错误"""
    pass


def interpolate(template: str, context: dict) -> str:
    """对单个字符串做模板插值 · 返回新字符串

    context 字段:
        ui:        dict[str, Any]    form 字段值
        upstream:  dict[str, dict]   node_id → outputs (workflow_engine 用)
        app_id:    str               当前 app id (secret 单段语法兜底用)
        ts:        str               时间戳 (可选 · 没传自动生成)
        secrets:   dict[str, str]    (可选) 测试时直接传入 · 避免触盘 · 生产走 app_secrets
    
    任何 ${} 占位符无法解析 (字段缺失且无 default) · 抛 TemplateError
    """
    if not isinstance(template, str):
        return template

    ui = context.get("ui") or {}
    inline_secrets = context.get("secrets") or {}
    upstream = context.get("upstream") or {}
    app_id = context.get("app_id") or ""
    ts = context.get("ts") or time.strftime("%Y%m%d_%H%M%S")
    ts_ms = context.get("ts_ms") or str(int(time.time() * 1000))

    def _resolve(m: re.Match) -> str:
        kind = m.group("kind")
        rest = (m.group("rest") or "").strip()

        if kind == "ui":
            if not rest:
                raise TemplateError(f"${{ui}} requires a field name")
            if ":" in rest:
                fname, _, default = rest.partition(":")
                fname = fname.strip()
                default = default.strip()
            else:
                fname = rest
                default = None
            if fname in ui and ui[fname] != "" and ui[fname] is not None:
                v = ui[fname]
                if isinstance(v, bool):
                    return "true" if v else "false"
                return str(v)
            if default is not None:
                return default
            raise TemplateError(f"ui field '{fname}' missing and no default")

        if kind == "secret":
            if not rest:
                raise TemplateError("${secret} requires a name")
            # 铁律 7 标准: ${secret:<app_id>:<name>} (跨 app 引用·显式)
            # 单段兜底: ${secret:<name>} 用 context.app_id (只能拿自己 app 的 secret)
            if ":" in rest:
                sec_app_id, _, sec_name = rest.partition(":")
                sec_app_id = sec_app_id.strip()
                sec_name = sec_name.strip()
            else:
                sec_app_id = app_id
                sec_name = rest
            if not sec_app_id:
                raise TemplateError(
                    f"${{secret:{rest}}} 没指定 app_id · 也没 context.app_id 兜底 · "
                    "写成 ${secret:<app_id>:<name>} (铁律 7 标准)"
                )
            # 测试注入 (inline_secrets={app_id: {name: value}} 或扁平 {name: value})
            if inline_secrets:
                if isinstance(inline_secrets.get(sec_app_id), dict):
                    v = inline_secrets[sec_app_id].get(sec_name)
                    if v not in (None, ""):
                        return str(v)
                elif sec_app_id == app_id and inline_secrets.get(sec_name) not in (None, ""):
                    return str(inline_secrets[sec_name])
            # 生产路径: 走 workers.app_secrets (跟 shell_exec 同一存储 · 跟铁律 7 对齐)
            try:
                from workers import app_secrets as _app_secrets
            except ImportError:
                raise TemplateError("workers.app_secrets 模块加载失败")
            try:
                val = _app_secrets.get_secret(sec_app_id, sec_name)
            except ValueError as e:
                raise TemplateError(f"secret 名字非法: {e}")
            if val is None or val == "":
                raise TemplateError(
                    f"secret '{sec_app_id}:{sec_name}' 没找到 · "
                    f"先跑 app_set_secret(app_id='{sec_app_id}', secret_name='{sec_name}', value='...') 落盘"
                )
            return str(val)

        if kind == "upstream":
            if ":" not in rest:
                raise TemplateError("${upstream} requires <node_id>:<port>")
            nid, _, port = rest.partition(":")
            outs = upstream.get(nid.strip()) or {}
            if port.strip() in outs:
                return str(outs[port.strip()])
            raise TemplateError(f"upstream {nid}:{port} not found")

        if kind == "app_id":
            return app_id

        if kind == "ts":
            return ts

        if kind == "ts_ms":
            return ts_ms

        raise TemplateError(f"unknown template kind: {kind}")

    return _PATTERN.sub(_resolve, template)


def interpolate_value(value: Any, context: dict) -> Any:
    """单值插值 · 含类型保留 fast-path
    
    如果 value 是字符串且整体就是单一 ${...} placeholder · 返回原生类型 (int/float/bool/dict/list)。
    例如 ${ui:n} 当 ui.n=1 (int) 时 · 返回 1 (int) 而不是 "1" (str)。
    
    字符串拼接 ("size=${ui:size}") 走原 interpolate · 必然返 str。
    """
    if not isinstance(value, str):
        return value

    m = _SINGLE_PATTERN.match(value)
    if not m:
        return interpolate(value, context)

    kind = m.group("kind")
    rest = (m.group("rest") or "").strip()
    ui = context.get("ui") or {}
    upstream = context.get("upstream") or {}
    app_id = context.get("app_id") or ""

    if kind == "ui":
        if not rest:
            raise TemplateError("${ui} requires a field name")
        if ":" in rest:
            fname, _, default = rest.partition(":")
            fname = fname.strip()
            default_raw = default.strip()
        else:
            fname = rest
            default_raw = None
        if fname in ui and ui[fname] != "" and ui[fname] is not None:
            return ui[fname]
        if default_raw is not None:
            return _try_parse_default(default_raw)
        raise TemplateError(f"ui field '{fname}' missing and no default")

    if kind == "upstream":
        if ":" not in rest:
            raise TemplateError("${upstream} requires <node_id>:<port>")
        nid, _, port = rest.partition(":")
        outs = upstream.get(nid.strip()) or {}
        port = port.strip()
        if port in outs:
            return outs[port]
        raise TemplateError(f"upstream {nid}:{port} not found")

    return interpolate(value, context)


def interpolate_deep(obj: Any, context: dict) -> Any:
    """递归插值 dict / list / 字符串 · 返回新对象

    其他类型 (int / float / bool / None) 原样返回。
    单值是字符串且整体是单一 ${...} placeholder 时 · 返回原生类型 (见 interpolate_value)。
    """
    if isinstance(obj, str):
        return interpolate_value(obj, context)
    if isinstance(obj, dict):
        return {k: interpolate_deep(v, context) for k, v in obj.items()}
    if isinstance(obj, list):
        return [interpolate_deep(v, context) for v in obj]
    return obj


def evaluate_when(when: str, ui: dict) -> bool:
    """计算 routes[].when 是否命中
    
    支持:
        'default'              → 总命中
        '<field>==<value>'     → ui[field] == value (字符串相等)
    """
    when = (when or "").strip()
    if when in ("", "default"):
        return True
    if "==" not in when:
        return False
    field, _, value = when.partition("==")
    field = field.strip()
    value = value.strip()
    actual = ui.get(field)
    if isinstance(actual, bool):
        actual_s = "true" if actual else "false"
    elif actual is None:
        actual_s = ""
    else:
        actual_s = str(actual)
    return actual_s == value
