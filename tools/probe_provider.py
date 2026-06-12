"""
probe_provider.py
=================

给一把不明身份的 API key，探测它属于哪家供应商，并列出可用模型。

用法：
  # 浅扫描：只看 /models 端点是否 200（快，但有假阳性——
  # 很多供应商的 /models 是公开端点，任何 key 都返回 200）
  python tools/probe_provider.py --key sk-xxx

  # 深扫描：在浅扫描通过的端点上真发一条 /chat/completions（准，但每家会花 ~$0.001）
  python tools/probe_provider.py --key sk-xxx --deep

  # 已知 base_url（最准）
  python tools/probe_provider.py --key sk-xxx --base-url https://api.ppinfra.com/v3/openai --deep

  # 只测 Anthropic 协议
  python tools/probe_provider.py --key sk-xxx --anthropic-only

依赖：httpx（已被 anthropic / openai SDK 拖进来，不需要额外装）

血泪教训（2026-05-15）：
  OpenRouter / AiHubMix 等很多供应商的 /models 是完全公开的——连空 key 都返回 200。
  仅靠 /models 200 OK 是假阳性，必须配 --deep 做真实 /chat/completions 验证。
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


# Known OpenAI-compatible providers. Order = probe priority.
# 注意：base_url 不带末尾斜杠；/models 是 OpenAI 规范的列表端点。
OPENAI_COMPAT_PROVIDERS: list[tuple[str, str]] = [
    ("OpenAI",       "https://api.openai.com/v1"),
    ("OpenRouter",   "https://openrouter.ai/api/v1"),
    ("PPIO",         "https://api.ppinfra.com/v3/openai"),
    ("DeepBricks",   "https://api.deepbricks.ai/v1"),
    ("AiHubMix",     "https://aihubmix.com/v1"),
    ("OneAPI-like",  "https://api.gptsapi.net/v1"),  # 常见 one-api 部署示例
]


def mask_key(key: str) -> str:
    if len(key) < 12:
        return "***"
    return f"{key[:6]}...{key[-4:]}  ({len(key)} chars)"


def probe_anthropic(key: str, base_url: str, timeout: float) -> dict[str, Any]:
    """Hit POST /v1/messages with minimal payload."""
    url = base_url.rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-5-20250929",
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "ping"}],
    }
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        return {"ok": False, "status": "timeout", "error": "network timeout"}
    except httpx.ConnectError as e:
        return {"ok": False, "status": "connect_error", "error": str(e)[:120]}
    except Exception as e:
        return {"ok": False, "status": "exception", "error": str(e)[:120]}

    if r.status_code == 200:
        try:
            data = r.json()
            reply = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    reply = block.get("text", "")[:60]
                    break
            return {"ok": True, "status": 200, "reply": reply, "claude_models": ["claude-sonnet-4-5-20250929"]}
        except Exception as e:
            return {"ok": False, "status": 200, "error": f"parse: {e}"}
    elif r.status_code == 401:
        return {"ok": False, "status": 401, "error": "invalid key (401)"}
    else:
        return {"ok": False, "status": r.status_code, "error": r.text[:140]}


def probe_openai_compat(name: str, base_url: str, key: str, timeout: float) -> dict[str, Any]:
    """GET /models on OpenAI-compatible endpoint. WARNING: /models is public on many providers."""
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(url, headers=headers)
    except httpx.TimeoutException:
        return {"ok": False, "status": "timeout", "error": "network timeout (VPN/firewall?)"}
    except httpx.ConnectError as e:
        return {"ok": False, "status": "connect_error", "error": str(e)[:120]}
    except Exception as e:
        return {"ok": False, "status": "exception", "error": str(e)[:120]}

    if r.status_code != 200:
        snippet = r.text[:140].replace("\n", " ")
        return {"ok": False, "status": r.status_code, "error": snippet}

    try:
        data = r.json()
    except Exception as e:
        return {"ok": False, "status": 200, "error": f"json parse: {e}"}

    # OpenAI shape: {"data": [{"id": "..."}, ...]} ; some providers omit "data"
    items = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {"ok": False, "status": 200, "error": "unexpected response shape"}

    all_ids = [m.get("id", "") for m in items if isinstance(m, dict)]
    claude_models = sorted([m for m in all_ids if "claude" in m.lower()])
    return {
        "ok": True,
        "status": 200,
        "models_count": len(all_ids),
        "claude_models": claude_models,
    }


def deep_verify_openai_compat(base_url: str, key: str, model: str, timeout: float) -> dict[str, Any]:
    """
    Send a real /chat/completions ping to verify the key.
    成本极小（~16 tokens 一次）。
    """
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://daemonkey.local",
        "X-Title": "Daemonkey-probe",
    }
    payload = {
        "model": model,
        "max_tokens": 5,
        "messages": [{"role": "user", "content": "ok"}],
    }
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        return {"ok": False, "status": "timeout"}
    except Exception as e:
        return {"ok": False, "status": "exception", "error": str(e)[:120]}

    if r.status_code == 200:
        try:
            data = r.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            return {"ok": True, "status": 200, "reply": reply[:60], "usage": usage}
        except Exception as e:
            return {"ok": False, "status": 200, "error": f"parse: {e}"}
    else:
        snippet = r.text[:200].replace("\n", " ")
        return {"ok": False, "status": r.status_code, "error": snippet}


def print_result(label: str, url: str, result: dict[str, Any]) -> None:
    if result["ok"]:
        if "claude_models" in result:
            cnt = result.get("models_count", len(result["claude_models"]))
            n_claude = len(result["claude_models"])
            print(f"      [ok]   200  ({cnt} models, {n_claude} claude)")
            if "reply" in result and result["reply"]:
                print(f"             round-trip ok, reply: {result['reply']!r}")
        else:
            print(f"      [ok]   {result['status']}")
    else:
        status = result.get("status", "?")
        err = result.get("error", "")
        print(f"      [fail] {status}  {err}")


def main() -> int:
    p = argparse.ArgumentParser(description="Probe an API key against known providers.")
    p.add_argument("--key", required=True, help="API key to probe")
    p.add_argument("--base-url", default="", help="Test only this base_url (skip default sweep)")
    p.add_argument("--anthropic-only", action="store_true", help="Only test Anthropic protocol")
    p.add_argument("--openai-only", action="store_true", help="Only test OpenAI-compatible endpoints")
    p.add_argument("--deep", action="store_true",
                   help="After shallow /models check passes, send a real /chat/completions to verify the key. "
                        "Costs ~$0.001 per match. Recommended.")
    p.add_argument("--timeout", type=float, default=8.0, help="Per-request timeout in seconds (default 8)")
    args = p.parse_args()

    print()
    print("  ============================================================")
    print(f"  OPUS Daemon · provider probe")
    print(f"  key: {mask_key(args.key)}")
    print("  ============================================================")

    matches: list[tuple[str, str, dict]] = []

    # === Case 1: user gave a base_url → only test that ===
    if args.base_url:
        url = args.base_url.rstrip("/")
        # heuristic: try Anthropic protocol if anthropic.com or user said so
        if args.anthropic_only or "anthropic" in url.lower():
            print(f"\n  [explicit] Anthropic-protocol  →  {url}")
            res = probe_anthropic(args.key, url, args.timeout)
            print_result("anthropic", url, res)
            if res["ok"]:
                matches.append(("Anthropic-compatible", url, res))
        else:
            print(f"\n  [explicit] OpenAI-compatible  →  {url}")
            res = probe_openai_compat("custom", url, args.key, args.timeout)
            print_result("custom", url, res)
            if res["ok"]:
                matches.append(("OpenAI-compatible", url, res))
    else:
        # === Case 2: no base_url → sweep ===
        # Anthropic first (different protocol)
        if not args.openai_only:
            print(f"\n  [1] Anthropic   (https://api.anthropic.com)")
            res = probe_anthropic(args.key, "https://api.anthropic.com", args.timeout)
            print_result("Anthropic", "https://api.anthropic.com", res)
            if res["ok"]:
                matches.append(("Anthropic", "https://api.anthropic.com", res))

        if not args.anthropic_only:
            for i, (name, url) in enumerate(OPENAI_COMPAT_PROVIDERS, start=2):
                print(f"\n  [{i}] {name}   ({url})")
                res = probe_openai_compat(name, url, args.key, args.timeout)
                print_result(name, url, res)
                if res["ok"]:
                    matches.append((name, url, res))

    # === Deep verification (optional but recommended) ===
    verified: list[tuple[str, str, dict]] = []
    shallow_rejected: list[tuple[str, str, dict]] = []

    if args.deep and matches:
        print()
        print("  ============================================================")
        print("  Deep verify: sending real /chat/completions (cost ~$0.001 each)")
        print("  ============================================================")
        for name, url, res in matches:
            if name in ("Anthropic", "Anthropic-compatible"):
                verified.append((name, url, res))
                continue
            claude = res.get("claude_models", [])
            if not claude:
                print(f"\n  [{name}] no Claude models -> skipping deep verify")
                shallow_rejected.append((name, url, res))
                continue
            model = next(
                (m for m in claude if "sonnet-4.5" in m or "sonnet-4-5" in m),
                claude[0],
            )
            print(f"\n  [{name}] POST /chat/completions  model={model}")
            deep = deep_verify_openai_compat(url, args.key, model, args.timeout)
            if deep["ok"]:
                reply = deep.get("reply", "")
                print(f"      [verified]  reply={reply!r}")
                usage = deep.get("usage", {})
                if usage:
                    print(f"      usage:      {usage}")
                verified.append((name, url, res))
            else:
                err = deep.get("error", "")[:120]
                print(f"      [REJECTED]  status={deep['status']}  {err}")
                shallow_rejected.append((name, url, res))
    elif matches:
        verified = matches  # trust shallow result if not deep

    # === Summary ===
    print()
    print("  ============================================================")
    if verified:
        print(f"  RESULT: {len(verified)} verified match(es)")
        if shallow_rejected:
            print(f"          ({len(shallow_rejected)} provider(s) had public /models but REJECTED the key)")
        print("  ============================================================")
        for name, url, res in verified:
            print(f"\n  [ok] {name}")
            print(f"       base_url: {url}")
            claude = res.get("claude_models", [])
            if claude:
                print(f"       Claude models exposed ({len(claude)}):")
                for m in claude[:20]:
                    print(f"         - {m}")
                if len(claude) > 20:
                    print(f"         ... and {len(claude) - 20} more")
            else:
                if "models_count" in res:
                    print(f"       (key valid but NO Claude models)")

        print()
        print("  ============================================================")
        print("  Next step:")
        print("    Add these lines to your .env:")
        first = verified[0]
        if first[0] in ("Anthropic", "Anthropic-compatible"):
            print(f"      ANTHROPIC_API_KEY={args.key[:6]}...{args.key[-4:]}")
        else:
            print(f"      OPUS_API_KEY={args.key[:6]}...{args.key[-4:]}")
            print(f"      OPUS_BASE_URL={first[1]}")
            claude = first[2].get("claude_models", [])
            if claude:
                preferred = next(
                    (m for m in claude if "sonnet-4.5" in m or "sonnet-4-5" in m),
                    claude[0],
                )
                print(f"      OPUS_MODEL={preferred}")
        print("  ============================================================")

        if not args.deep:
            print()
            print("  WARNING: shallow scan only. /models is public on many providers—")
            print("  these 'matches' may be FALSE POSITIVES. Re-run with --deep to verify.")
            print("  ============================================================")
        return 0
    else:
        if shallow_rejected:
            print(f"  RESULT: ALL shallow matches REJECTED in deep verify")
        else:
            print(f"  RESULT: no matches")
        print("  ============================================================")
        if shallow_rejected:
            print("  Providers that PRETENDED to accept your key (public /models endpoint):")
            for name, url, _ in shallow_rejected:
                print(f"    - {name}  ({url})")
            print()
            print("  Translation: this key is NOT valid on any of the providers in our list.")
        print("  Possible reasons:")
        print("    1. Key belongs to a provider not in our default list.")
        print("       -> re-run with --base-url <your-actual-provider-url> --deep")
        print("    2. Network blocks every endpoint (VPN state?)")
        print("    3. Key is expired / revoked / quota exhausted.")
        print("    4. Key works only on one specific (private) endpoint.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
