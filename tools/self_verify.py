"""
tools/self_verify.py
====================

卷四十六 III 补丁 5 · 一键自测 · 验 11 个新 commit 是否都跑通

跑法 (推荐):
    双击项目根目录的 verify.bat

跑法 (命令行):
    cd 到项目根目录
    .\\.venv\\Scripts\\python.exe tools\\self_verify.py

它做的事:
  1. 自动从 .env 读 OPUS_API_TOKEN
  2. 检查 daemon 是不是在 7860 跑着 (没在 → 提示先启 start.bat)
  3. 跑 11 类 endpoint 检查 · 每条输出 [OK] / [FAIL]
  4. 跑完汇总 PASS/FAIL · 退出码 0 = 全过 · 1 = 有失败

不调真 LLM · 不花钱 · 不动你的 session。

如果 daemon 没启 · 用 TestClient fallback 模式自测 (in-process · 不打 7860)。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_TOKEN_FROM_ENV: str | None = None
DEFAULT_PORT = 7860

passed = 0
failed = 0
failures: list[str] = []


def log_ok(name: str, detail: str = "") -> None:
    global passed
    passed += 1
    extra = f"  ({detail})" if detail else ""
    print(f"  [OK]   {name}{extra}")


def log_fail(name: str, detail: str = "") -> None:
    global failed
    failed += 1
    failures.append(name)
    extra = f"  ({detail})" if detail else ""
    print(f"  [FAIL] {name}{extra}")


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        log_ok(name, detail)
    else:
        log_fail(name, detail)


def _read_token() -> str:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("OPUS_API_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def _detect_running_daemon(port: int) -> str | None:
    """尝试连 7860 · 通就返回 'http://127.0.0.1:<port>' · 不通返 None"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.8)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return f"http://127.0.0.1:{port}"
    except (socket.error, OSError):
        return None


def _make_real_client(base_url: str, token: str):
    """生成一个调真 HTTP 的 client · 用 httpx (requirements.txt 里有)"""
    import httpx
    headers = {"Authorization": f"Bearer {token}"}
    return httpx.Client(base_url=base_url, headers=headers, timeout=10.0)


def _make_test_client(token: str):
    """fallback: 用 TestClient · 不连 7860 · in-process 验路由"""
    from fastapi.testclient import TestClient
    os.environ["OPUS_API_TOKEN"] = token or "self-verify-fallback-token-32-chars"
    from daemon_api import build_app
    app = build_app()

    class _Wrapper:
        def __init__(self, c, tok):
            self._c = c
            self._h = {"Authorization": f"Bearer {tok}"}

        def get(self, path, headers=None):
            h = dict(self._h)
            if headers:
                h.update(headers)
            return self._c.get(path, headers=h)

        def post(self, path, json=None, headers=None):
            h = dict(self._h)
            if headers:
                h.update(headers)
            return self._c.post(path, json=json, headers=h)

    return _Wrapper(TestClient(app), os.environ["OPUS_API_TOKEN"])


def run_checks(client, mode: str) -> None:
    print(f"\n===== mode: {mode} =====")

    # R1 logging
    print("\n[R1] /api/logs/tail")
    r = client.get("/api/logs/tail?lines=5")
    check("GET 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        check(
            "  含 lines 字段",
            "lines" in body or "ok" in body,
            f"keys={list(body.keys())[:5]}",
        )

    # R4-A watchdog
    print("\n[R4-A] /api/lifecycle_status")
    r = client.get("/api/lifecycle_status")
    check("GET 200", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        sh = body.get("scheduler_health")
        check("  scheduler_health 字段存在", sh is not None)
        if sh:
            check(
                "  scheduler_health.radar 结构对",
                isinstance(sh.get("radar"), dict) and "alive" in sh["radar"],
            )
            check("  overall_stuck 是 bool", isinstance(sh.get("overall_stuck"), bool))

    # Y2 token budget
    print("\n[Y2] /api/token_budget")
    r = client.get("/api/token_budget/status")
    check("status GET 200", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        check("  limits.session 是 int", isinstance(body.get("limits", {}).get("session"), int))
        check(
            "  default disabled",
            body["limits"]["session"] == 0 and body["limits"]["day"] == 0,
            "改 env OPUS_TOKEN_BUDGET_SESSION 启用",
        )

    # Y6 .env hot reload
    print("\n[Y6] /api/env/reload_status")
    r = client.get("/api/env/reload_status")
    check("GET 200", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        check("  reload_count 字段", "reload_count" in body)
        check("  hot_keys 是列表", isinstance(body.get("hot_keys"), list))
        check(
            "  hot_keys 含 OPUS_API_DEFAULT_CONFIRM",
            "OPUS_API_DEFAULT_CONFIRM" in (body.get("hot_keys") or []),
        )

    # Y7 rate limit
    print("\n[Y7] /api/ratelimit + /api/audit")
    r = client.get("/api/ratelimit/status")
    check("ratelimit GET 200", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        check(
            "  config.enabled 字段",
            "config" in body and "enabled" in body["config"],
        )
        check(
            "  default disabled",
            body["config"]["enabled"] is False,
            "改 env OPUS_RATELIMIT_PER_MIN 启用",
        )

    r = client.get("/api/audit/recent?n=5")
    check("audit GET 200", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        check("  含 enabled 字段", "enabled" in body)
        check("  items 是列表", isinstance(body.get("items"), list))

    # R3 session repair
    print("\n[R3] /api/session/repair (dry_run 不存在的 session)")
    r = client.post(
        "/api/session/repair",
        json={"session_id": "nonexistent-self-verify", "dry_run": True},
    )
    check("不应 5xx", r.status_code < 500, f"status={r.status_code}")

    # /chat 鉴权回归 (Y7 bug 修复后)
    print("\n[Y7-fix] /chat 鉴权回归")
    # 无 token → 401
    r = client.post("/chat", json={"message": "hi"}, headers={"Authorization": ""})
    check("/chat no-token → 401", r.status_code == 401, f"status={r.status_code}")
    # 无 message → 400
    r = client.post("/chat", json={})
    check("/chat no-message → 400", r.status_code == 400, f"status={r.status_code}")

    # 老 endpoint 不破
    print("\n[regression] 老 endpoint 不破")
    r = client.get("/")
    check("GET / 200", r.status_code == 200)
    r = client.get("/status")
    check("GET /status 200", r.status_code == 200)
    r = client.get("/sessions?api_only=true")
    check("GET /sessions 200", r.status_code == 200)

    # R5 备份
    print("\n[R5] data/_backups/")
    backups = ROOT / "data" / "_backups"
    if backups.exists():
        baks = list(backups.glob("*.bak"))
        check(f"  备份文件 {len(baks)} 个", len(baks) > 0)
    else:
        log_fail("  data/_backups/ 不存在", "需要先触发一次 wishlist / opp / outcomes 写入")


def main() -> int:
    print("=" * 64)
    print(" SELF-VERIFY · 卷四十六 III 补丁 5 · 14 commit 自测")
    print("=" * 64)

    token = _read_token()
    if not token:
        print("\n[FAIL] 读不到 OPUS_API_TOKEN · 检查 .env 文件")
        return 2

    base = _detect_running_daemon(DEFAULT_PORT)

    if base:
        print(f"\n  ✓ 发现 daemon 在跑: {base}")
        print("  → 用真 HTTP client 测 (走完整网络栈)")
        try:
            client = _make_real_client(base, token)
        except ImportError:
            print("  ✗ httpx 没装 · fallback 到 TestClient (in-process)")
            client = _make_test_client(token)
            run_checks(client, mode="TestClient (httpx 缺)")
        else:
            run_checks(client, mode=f"REAL HTTP · {base}")
    else:
        print(f"\n  ✗ 端口 {DEFAULT_PORT} 没 daemon (双击 start.bat 启一个)")
        print("  → fallback: TestClient (in-process · 不需要 daemon 跑)")
        client = _make_test_client(token)
        run_checks(client, mode="TestClient (in-process)")

    print()
    print("=" * 64)
    print(f" 自测完毕 · {passed} PASS · {failed} FAIL")
    if failures:
        print("\n  失败项:")
        for f in failures:
            print(f"    - {f}")
    print("=" * 64)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
