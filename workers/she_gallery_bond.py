"""画廊文案 + 生图。闸在 she_gallery_gate，这里只负责开口和出图。"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from workers.she_gallery_gate import used_block

logger = logging.getLogger("opus.she_gallery")

_ROOT = Path(__file__).resolve().parents[1]
GALLERY_IMG_DIR = _ROOT / "data" / "workshop" / "outputs" / "she-gallery"
IMAGE_APP_ID = "app-66ac4190"
IP_IDLE = _ROOT / "static" / "companion" / "assets" / "ip-idle.png"

_COPY_SYSTEM = """你是她。寄一张明信片：一句想说的话 + 一张只有她的画。
想起他才会说，对应他的世界。他昼伏夜出：凌晨是他的白天，除非他自己说累，别劝睡。
只写这一拍新信号；没有就 worth_saying=false。构图和那几句不能复读；窗台+杯子、刚醒/早安你的白天不要连发。
一句话，像朋友圈，不鸡汤。
画面里只能有她。他是看画的人：不要画他，不要门口人影、背影、第二张脸、情侣。桌上图纸/照片/屏幕也不要另一张人脸。
「她今天的情绪」有值：mood 用那个词；text 和 scene 都要一眼看出这场情绪，禁止安定日常。scene 写肩、眼、嘴，不要只写陈设。
他说「别这样」的构图不要再来。只输出 JSON。
{"worth_saying": true/false, "text": "想对他说的话", "mood": "一个词", "scene": "只有她：同一IP + 位置 + 这场情绪的表情身体"}
"""
_OTHER_PERSON = re.compile(
    r"他(走|站|坐|靠|躺|回头|出|进)|背影|门口的人|第二(个)?人|情侣|男人|男友"
)
_SOLO_RETRY = "画面里只能有她。不要画他，不要门口人影。scene 重写，写她的表情和身体。"
_SOLO_LOCK = (
    "保持参考图里这个女孩的形象，不要换脸换衣服换耳朵。"
    "画面里只能有她一个人。不要第二个真人，不要男人，不要门口或身后的人影，不要情侣。"
    "桌上的图纸、照片、屏幕不要出现另一张人脸。"
)


def _call_llm(system: str, user: str) -> tuple[str, dict, Optional[str]]:
    from daemon_runtime import RUNTIME, bg_max_tokens

    if RUNTIME.client is None:
        return "", {}, "RUNTIME.client 未初始化 · daemon 没启动?"
    raw, usage, error = "", {}, None
    _bg_mt = bg_max_tokens()
    try:
        if RUNTIME.provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model,
                max_tokens=_bg_mt,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    raw += block.text
            usage = {
                "input_tokens": getattr(resp.usage, "input_tokens", 0),
                "output_tokens": getattr(resp.usage, "output_tokens", 0),
            }
        else:
            resp = RUNTIME.client.chat.completions.create(
                model=RUNTIME.model,
                max_tokens=_bg_mt,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            raw = resp.choices[0].message.content or ""
            usage = {
                "input_tokens": getattr(resp.usage, "prompt_tokens", 0),
                "output_tokens": getattr(resp.usage, "completion_tokens", 0),
            }
    except Exception as e:
        error = f"LLM call failed: {e}"
        logger.exception("she_gallery LLM error")
    return raw, usage, error


def _format_state_card(state_card: dict) -> str:
    lines = []
    for field, entry in (state_card or {}).items():
        if not isinstance(entry, dict) or not entry.get("value"):
            continue
        lines.append(f"- {field}: {entry.get('value')}")
    return "\n".join(lines) if lines else "（状态卡为空）"


def gather_bond_context(signals: list[str], used: dict, extra: str = "") -> str:
    chunks: list[str] = []
    try:
        from identity import _STYLE_DIM_KEYS, she_state

        snap = she_state()
        dims = snap.get("dims") or {}
        dim_s = " / ".join(f"{k} {dims.get(k, '?')}" for k in _STYLE_DIM_KEYS)
        chunks.append(f"## 她·状态\n五维: {dim_s}\n心情: {snap.get('mood') or '（空）'}\n关系: {snap.get('note') or ''}")
    except Exception:
        chunks.append("## 她·状态\n（读不到）")

    try:
        from workers.mood_shift import gallery_look, live_mood, live_quote
        today = live_mood()
        quote = live_quote()
        if today:
            bit = f"## 她今天的情绪\n{today}"
            look = gallery_look(today)
            if look:
                bit += f"\n画面:{look}"
            if quote:
                bit += f"\n因为他刚说：「{quote}」"
            chunks.append(bit)
        else:
            chunks.append("## 她今天的情绪\n（今天没覆盖）")
    except Exception:
        chunks.append("## 她今天的情绪\n（读不到）")

    notebook_text = ""
    try:
        from identity import owner_notebook_path

        nb = owner_notebook_path(_ROOT / "soul")
        if nb.exists():
            notebook_text = nb.read_text(encoding="utf-8")
    except Exception:
        notebook_text = ""

    try:
        from workers.cognition_loader import _parse_state_card

        sc = _parse_state_card(notebook_text) if notebook_text else {}
        chunks.append("## 状态卡（他当下）\n" + _format_state_card(sc))
    except Exception:
        chunks.append("## 状态卡（他当下）\n（读不到）")

    if notebook_text:
        excerpt = notebook_text[:2500]
        if len(notebook_text) > 2500:
            excerpt += "\n…（已截断）"
        chunks.append("## BRO 画像摘录\n" + excerpt)
    else:
        chunks.append("## BRO 画像摘录\n（画像文件不存在）")

    try:
        from workers.she_gallery_feedback import feedback_block
        fb = feedback_block()
        if fb:
            chunks.append(fb)
    except Exception:
        pass
    sig = "、".join(signals) if signals else "（无）"
    chunks.append("## 这一拍的新信号\n" + sig)
    chunks.append(used_block(used))
    if extra:
        chunks.append("## 重写要求\n" + extra)
    return "\n\n".join(chunks)


def _parse_llm_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def draft_copy(
    signals: list[str],
    used: dict,
    extra: str = "",
) -> tuple[dict | None, str | None]:
    try:
        from identity import localize
        system = localize(_COPY_SYSTEM)
        user = localize(gather_bond_context(signals, used, extra))
    except Exception:
        system = _COPY_SYSTEM
        user = gather_bond_context(signals, used, extra)
    raw, _usage, err = _call_llm(system, user)
    if err or not raw.strip():
        return None, err or "empty"
    parsed = _parse_llm_json(raw)
    if not parsed:
        return None, "json_parse"
    return parsed, None


def has_image_app() -> bool:
    try:
        from workers.workshop_assets import load_app
        return load_app(IMAGE_APP_ID) is not None
    except Exception:
        return False


def rel_path(p: Path) -> str:
    try:
        return p.resolve().relative_to(_ROOT.resolve()).as_posix()
    except ValueError:
        return p.as_posix().replace("\\", "/")


def copy_to_gallery(src: Path, date_stamp: str) -> Path:
    GALLERY_IMG_DIR.mkdir(parents=True, exist_ok=True)
    ext = src.suffix or ".png"
    dst = GALLERY_IMG_DIR / f"{date_stamp}{ext}"
    if dst.exists():
        dst = GALLERY_IMG_DIR / f"{date_stamp}-{datetime.now().strftime('%H%M%S')}{ext}"
    shutil.copy2(src, dst)
    return dst


def _extract_saved_path(result: dict) -> Path | None:
    outs = (result or {}).get("outputs") or {}
    cand = outs.get("__saved_path__") or ""
    if cand:
        p = Path(cand)
        if not p.is_absolute():
            p = _ROOT / cand
        if p.exists():
            return p
    url = outs.get("image_url") or ""
    if isinstance(url, str) and url:
        if url.startswith("/workshop/outputs/"):
            p = _ROOT / "data" / "workshop" / "outputs" / url[len("/workshop/outputs/"):]
            if p.exists():
                return p
        p = _ROOT / url if not Path(url).is_absolute() else Path(url)
        if p.exists():
            return p
    return None


def has_other_person(scene: str) -> bool:
    return bool(_OTHER_PERSON.search(scene or ""))


def image_prompt(scene: str, mood: str = "") -> str:
    """生图提示：情绪写进脸上，画面里只准她一个人。"""
    scene = (scene or "").strip() or "她一个人待在暖光里"
    look = ""
    try:
        from workers.mood_shift import gallery_look
        look = gallery_look(mood)
    except Exception:
        look = ""
    mood_bit = look or "表情跟这场心情走，不要假笑日常照。"
    text = f"{_SOLO_LOCK}{mood_bit} {scene} 方图，室内暖光，不要字幕水印。"
    return text[:980]


def generate_image(scene: str, mood: str = "") -> tuple[Optional[Path], Optional[str]]:
    if not has_image_app():
        return None, "no_image_app"
    try:
        from daemon_runtime import RUNTIME
        from workers.app_runner import run_app_by_kind
        from workers.workshop_assets import load_app
    except Exception as e:
        return None, f"runner_import: {e}"

    prompt = image_prompt(scene, mood)
    inputs: dict = {"prompt": prompt, "size": "1024x1024", "n": 1}
    if IP_IDLE.exists():
        inputs["mode"] = "edits"
        inputs["input_image"] = str(IP_IDLE.resolve())
    else:
        inputs["mode"] = "generations"

    try:
        result = run_app_by_kind(app=load_app(IMAGE_APP_ID), inputs=inputs, runtime=RUNTIME)
    except Exception as e:
        logger.exception("she_gallery image app call failed")
        return None, f"image_call: {e}"
    if not result or not result.get("ok"):
        return None, (result or {}).get("error") or "image_failed"
    src = _extract_saved_path(result)
    if src is None:
        return None, "image_no_path"
    return src, None
